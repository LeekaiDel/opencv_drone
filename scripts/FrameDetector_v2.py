#!/usr/bin/env python
#coding=utf8

import cv2 as cv
import numpy as np
import rospy
import math
import tf


from visualization_msgs.msg import Marker
from cv_bridge import CvBridge
from sensor_msgs.msg import Image
from geometry_msgs.msg import PoseStamped, Point
from opencv_drone.msg import frame_detect
from drone_msgs.msg import Goal                 	    #kill#

drone_pose_topic = "/mavros/local_position/pose"        #kill#
depth_image_topic = "/d400/depth/image_rect_raw"     	#/camera/aligned_depth_to_infra1/image_raw
image_topic = "/d400/color/image_raw"
drone_goal_pose = "/goal_pose"                          #kill#
frame_detect_topic = "/frame_detector"

view_result_flag = True
debug_prints = False

marker_publisher = None
contours = None
depth_frame = None
image_binary = None
rgb_image = None

yaw_error = 0.0
old_time = 0.0
last_area = 0.0
l = 1.1                # Плечо рамки в метрах
height_of_drone = 0.6  # Высота дрона
width_of_drone = 0.8   # Ширина дрона
image_width_px = 1280
image_height_px = 720

goal_pose = Goal()
frame_detect_flag = frame_detect()

# классы для функции пролета в рамку
class goal:
    def __init__(self, x0, y0, z0, x1, y1, z1):
        self.x0 = x0
        self.y0 = y0
        self.z0 = z0

        self.x1 = x1
        self.y1 = y1
        self.z1 = z1


class pointsFrame:
    def __init__(self, x, y):
        self.x = x
        self.y = y


class pointsDrone:
    def __init__(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z


def rgb_image_cb(data):
    global rgb_image
    try:
        bridge = CvBridge()
        rgb_image = bridge.imgmsg_to_cv2(data, desired_encoding='bgr8')
    except Exception as e:
        print ("Error read rgb_image", e)
        rgb_image = None


# берем конфигурацию основных переменных из сервера параметров ROS
def get_params_server():
    global depth_image_topic, view_result_flag, image_width_px, image_height_px

    depth_image_topic = rospy.get_param('~depth_image_topic', depth_image_topic)
    view_result_flag = rospy.get_param('~view_result_flag', view_result_flag)
    image_width_px = rospy.get_param('~image_width_px', image_width_px)
    image_height_px = rospy.get_param('~image_height_px', image_height_px)

    rospy.loginfo("init params done")


def depth_image_cb(data):
    global image_binary, depth_frame, opening
    try:
        bridge = CvBridge()
        # переводим фрейм из росовского сообщения в картинку opencv
        depth_image = bridge.imgmsg_to_cv2(data, "32FC1")
        depth_frame = np.array(depth_image, dtype=np.float32)   # каждый элемент фрейма хранит значение типа float являющееся расстоянием в метрах до точки

        image_binary = np.zeros_like(depth_frame)
        # делаем маску из допустимых пикселей на основе условия

        image_binary[(depth_frame < 4500.0) & (depth_frame > 100.0)] = 255          #3000:100
                                    
        # print 1

        image_binary = np.array(image_binary, dtype=np.uint8)

        kernel = np.ones((30, 30), np.uint8)

        kernel_dilation = np.ones((10, 10), np.uint8)

        opening = cv.erode(image_binary, kernel_dilation, iterations=1)

        opening = cv.dilate(opening, kernel_dilation, iterations=1)

        # opening = cv.morphologyEx(opening, cv.MORPH_OPEN, kernel)

        kernel_second = np.ones((30, 30), np.uint8)

        opening = cv.morphologyEx(opening, cv.MORPH_CLOSE, kernel_second)

        kernel_erode = np.ones((12, 12), np.uint8)
        opening = cv.erode(opening, kernel_erode, iterations=1)

    except:
        print ("Error read depth image")
        image_binary = None


# функция считывания текущего положения дрона
def drone_pose_cb(data):
    global drone_pose, quaternion, roll, pitch, yaw
    drone_pose = data
    quaternion = (
        data.pose.orientation.x,
        data.pose.orientation.y,
        data.pose.orientation.z,
        data.pose.orientation.w)
    (roll, pitch, yaw) = tf.transformations.euler_from_quaternion(quaternion)
    # print("pitch-> ", pitch)

def calculateGoalPointToFrame(size_x, size_y, pointsFrame, dist, l, height, width):
    global ang
    '''
    Функция от В.В.
    '''
    # Ищем ближайшую точку рамки к дрону
    d_min = min(dist)
    idx_min = list(dist).index(d_min)

    # print "d_min : " + str(d_min)
    # print "idx_min : " + str(idx_min)

    x1_min = 1000
    x2_min = 1000
    idx1_min = -1
    idx2_min = -1

    for i in range(0, 2):
        if pointsFrame.x[i] < x1_min:
            x1_min = pointsFrame.x[i]
            idx1_min = i
        elif pointsFrame.x[i] < x2_min:
            x2_min = pointsFrame.x[i]
            idx2_min = i

    k = l / math.sqrt((pointsFrame.x[idx1_min] - pointsFrame.x[idx2_min]) ** 2 + (pointsFrame.y[idx1_min] - pointsFrame.y[idx2_min]) ** 2)

    # print "k : " + str(k)

    # Считаем координаты точек рамки относительно дрона
    x = [0 for x in range(0, len(dist))]                              # [0.0, 0.0, 0.0, 0.0]
    y = [0 for y in range(0, len(dist))]
    z = [0 for z in range(0, len(dist))]

    for i in range(0, len(dist)):
        # print "pointsFrame.x[i] : " + pointsFrame.x[i]
        # print "pointsFrame.y[i] : " + pointsFrame.y[i]
        # print "size_x : " + size_x
        # print "size_y : " + size_y

        d_norm = math.sqrt((((pointsFrame.x[i] - size_x / 2) * k ) ** 2) + (((pointsFrame.y[i] - size_y / 2) * k) ** 2) + d_min ** 2)

        # print "d_norm : " + str(d_norm)

        x[i] = d_min + (dist[i] / d_min - 1)
        y[i] = (size_x / 2 - pointsFrame.x[i]) * k * dist[i] / d_norm
        z[i] = (size_y / 2 - pointsFrame.y[i]) * k * dist[i] / d_norm

    # print('x : ' + str(x))
    # print('y : ' + str(y))
    # print('z : ' + str(z))

    pointsDrone_ = pointsDrone(x, y, z)

    # Находим вектор нормали к плоскости рамки
    ax = pointsDrone_.x[1] - pointsDrone_.x[0]
    ay = pointsDrone_.y[1] - pointsDrone_.y[0]
    az = pointsDrone_.z[1] - pointsDrone_.z[0]
    bx = pointsDrone_.x[2] - pointsDrone_.x[0]
    by = pointsDrone_.y[2] - pointsDrone_.y[0]
    bz = pointsDrone_.z[2] - pointsDrone_.z[0]
    nx = ay * bz - by * az
    ny = bx * az - bz * ax
    nz = ax * by - ay * bx

    # print('nx : ' + str(nx))
    # print('ny : ' + str(ny))
    # print('nz : ' + str(nz))

    # Находим координаты центра рамки
    x_c = math.fsum(pointsDrone_.x) / 4
    y_c = math.fsum(pointsDrone_.y) / 4
    z_c = math.fsum(pointsDrone_.z) / 4

    # print('x_c : ' + str(x_c))
    # print('y_c : ' + str(y_c))
    # print('z_c : ' + str(z_c))

    # Находим точку p, удаленную от центра рамки на величину 1,25*width к дрону по направлению нормали
    n_norm = math.sqrt(math.pow(nx, 2) + math.pow(ny, 2) + math.pow(nz, 2))
    px1 = x_c - nx * 1.5 * width / n_norm
    py1 = y_c - ny * 1.5 * width / n_norm
    pz1 = z_c - nz * 1.5 * width / n_norm

    px2 = x_c + nx * 1.5 * width / n_norm
    py2 = y_c + ny * 1.5 * width / n_norm
    pz2 = z_c + nz * 1.5 * width / n_norm

    d1 = math.sqrt(math.pow(px1, 2) + math.pow(py1, 2) + math.pow(pz1, 2))
    d2 = math.sqrt(math.pow(px2, 2) + math.pow(py2, 2) + math.pow(pz2, 2))

    if d1 < d2:
        px = px1
        py = py1
        pz = pz1

    else:
        px = px2
        py = py2
        pz = pz2

    # print('px : ' + str(px))
    # print('py : ' + str(py))
    # print('pz : ' + str(pz))

    # Ищем угол между вектором нормали и вектором от дрона к точке p
    mx = x_c - px
    my = y_c - py
    mz = z_c - pz
    qx = -px
    qy = -py
    qz = -pz

    ang = math.acos((mx * qx + my * qy + mz * qz) / (math.sqrt(math.pow(mx, 2) + math.pow(my, 2) + math.pow(mz, 2)) * math.sqrt(math.pow(qx, 2) + math.pow(qy, 2) + math.pow(qz, 2))))
    #print('ang : ' + str(ang))

    # Если ang больше 165 градусов, то летим к центру рамки, в противном случае летим в точку p
    goal_ = goal(0, 0, 0, 0, 0, 0)

    # записываем координаты центра рамки в объект целевой точки
    goal_.x1 = x_c
    goal_.y1 = y_c
    goal_.z1 = z_c

    # print("ANGLE: %s" %ang)

    # if ang > 170 * math.pi / 180:
    #     goal_.x0 = x_c
    #     goal_.y0 = y_c
    #     goal_.z0 = z_c
    #
    # else:
    goal_.x0 = px
    goal_.y0 = py
    goal_.z0 = pz

    return goal_


def make_marker(point, id):
    marker = Marker()
    marker.header.frame_id = "/base_link"
    marker.type = marker.SPHERE
    marker.action = marker.ADD
    marker.id = id
    marker.scale.x = 0.76
    marker.scale.y = 0.76
    marker.scale.z = 0.76
    marker.color.a = 1.0
    marker.color.r = 1.0
    marker.color.g = 1.0
    marker.color.b = 0.0
    marker.pose.orientation.w = 1.0
    marker.pose.position.x = point.x
    marker.pose.position.y = point.y
    marker.pose.position.z = point.z

    return marker


def transform_cords_3D(X, Y, Z, roll, pitch, yaw, goal_, yaw_error):
    # glob_cords = np.array([X, Y, Z])

    local_cords_0 = np.array([goal_.x0, goal_.y0, goal_.z0])
    local_cords_1 = np.array([goal_.x1, goal_.y1, goal_.z1])
    local_cords_2 = np.array([goal_.x1 + 1.5 * math.cos(yaw_error), goal_.y1 + 1.5 * math.sin(yaw_error), goal_.z1])

    # transpose_cord = local_cords_0.reshape(3, 1)
    matrix_R = np.array([[math.cos(roll) * math.cos(yaw) - math.sin(roll) * math.cos(pitch) * math.sin(yaw), - math.cos(roll) * math.sin(yaw) - math.sin(roll) * math.cos(pitch) * math.cos(yaw), math.sin(roll) * math.sin(pitch)],
                         [math.sin(roll) * math.cos(yaw) + math.cos(roll) * math.cos(pitch) * math.sin(yaw), - math.sin(roll) * math.sin(yaw) + math.cos(roll) * math.cos(pitch) * math.cos(yaw), - math.cos(roll) * math.sin(pitch)],
                         [math.sin(pitch) * math.sin(yaw), math.sin(pitch) * math.cos(yaw), math.cos(pitch)]])


    glob_cords_of_point0 = np.dot(matrix_R, local_cords_0)
    glob_cords_of_point1 = np.dot(matrix_R, local_cords_1)
    glob_cords_of_point2 = np.dot(matrix_R, local_cords_2)


    glob_cords_of_point0 = [glob_cords_of_point0[0] + X, glob_cords_of_point0[1] + Y, glob_cords_of_point0[2] + Z]
    glob_cords_of_point1 = [glob_cords_of_point1[0] + X, glob_cords_of_point1[1] + Y, glob_cords_of_point1[2] + Z]
    glob_cords_of_point2 = [glob_cords_of_point2[0] + X, glob_cords_of_point2[1] + Y, glob_cords_of_point2[2] + Z]

    glob_cords_of_points = [glob_cords_of_point0, glob_cords_of_point1, glob_cords_of_point2]

    # print "glob_cords -> ", glob_cords_of_point
    return glob_cords_of_points


def trajectory_publisher(trajectory, yaw_error):
    global goal_pose_pub, drone_pose, detect_frame_publisher, frame_detect_flag

    flag_corrector_course = False

    while True:
        if len(trajectory) != 0:

            x = trajectory[0][0]
            y = trajectory[0][1]
            z = trajectory[0][2]

            del trajectory[0]

            goal_pose.pose.point.x = x
            goal_pose.pose.point.y = y
            goal_pose.pose.point.z = z

            # print z

            if flag_corrector_course is not True:
                goal_pose.pose.course = yaw + yaw_error
                flag_corrector_course = True
            else:
                goal_pose.pose.course = yaw

            while True:
                if abs(goal_pose.pose.point.x - drone_pose.pose.position.x) > 0.2 or abs(
                        goal_pose.pose.point.y - drone_pose.pose.position.y) > 0.2 or abs(
                        goal_pose.pose.point.z - drone_pose.pose.position.z) > 0.2:

                    goal_pose_pub.publish(goal_pose)
                else:
                    break
        else:
            frame_detect_flag.detect_frame = False
            detect_frame_publisher.publish(frame_detect_flag)
            break


def main():
    global old_time, last_area, goal_pose, goal_pose_pub, detect_frame_publisher
    rospy.init_node("Frame_detector_node")

    hz = rospy.Rate(30)

    get_params_server()

    # init subscribers
    rospy.Subscriber(depth_image_topic, Image, depth_image_cb)
    rospy.Subscriber(drone_pose_topic, PoseStamped, drone_pose_cb)  #kill#
    # init publishers
    goal_pose_pub = rospy.Publisher(drone_goal_pose, Goal, queue_size=10)       #Kill#
    detect_frame_publisher = rospy.Publisher(frame_detect_topic, frame_detect, queue_size=10)
    marker_publisher = rospy.Publisher('window_target_marker', Marker)

    while not rospy.is_shutdown():
        if depth_frame is not None and image_binary is not None:
            try:
                edges = cv.Canny(opening, 150, 200)
                # Увеличиваем контуры белых объектов (Делаем противоположность функции erode) - делаем две итерации
                edges = cv.dilate(edges, None, iterations=1)

                if view_result_flag:
                    # cv.imshow("test", opening)
                    cv.imshow("depth", opening)

            except:
                continue
            
            contours, _ = cv.findContours(edges, cv.RETR_TREE, cv.CHAIN_APPROX_SIMPLE)

            if len(contours):
                zeroes_mask = np.zeros_like(image_binary)

                contours = sorted(contours, key=cv.contourArea, reverse=True)
                # rospy.loginfo(len(contours))
                # фильтруем плохие контуры
                list_cnt = []
                for i in contours:
                    if cv.contourArea(i) > 30000.0 and cv.contourArea(i) < 100000.0:
                        list_cnt.append(i)
                if len(list_cnt) == 0:
                    continue

                # print len(list_cnt)
                hull = cv.convexHull(list_cnt[0])
                epsilon = 0.1 * cv.arcLength(hull, True)
                approx = cv.approxPolyDP(hull, epsilon, True)
                # print("AAAAAAAAAAAA-> %s" %len(approx))

                ###
                # найдем производные от площади контура, чтобы понять есть ли резкий скочек площади, что будет означать, что контур детектируется недостаточно хорошо
                dt = rospy.get_time() - old_time
                old_time = rospy.get_time()
                Ft = ((cv.contourArea(approx) - last_area) / 1000) / dt
                last_area = cv.contourArea(approx)
                # rospy.loginfo("Ft: %s" %abs(Ft))
                if Ft > 300.0:
                    rospy.loginfo("Area pick!")
                    continue
                ###

                cv.drawContours(zeroes_mask, [approx], -1, 255, 3)
                # zeroes_mask = cv.dilate(zeroes_mask, None, iterations=8)

                # cv.imshow("Fuck", zeroes_mask)

                # ищем хорошие точки для трекинга в углах рамки
                corners = cv.goodFeaturesToTrack(zeroes_mask, 4, 0.4, 10)  # return [x:640, y:480]      #corners = cv.goodFeaturesToTrack(gray, 4, 0.01, 10)
                try:
                    corners = np.int0(corners)
                except:
                    rospy.loginfo("Huy znaet chto emu nugno")
                if cv.contourArea(approx) > 30000.0 and corners is not None:
                    rospy.loginfo("Detect frame")
                    try:
                        corners = corners.reshape(4, -1)
                        image_binary_copy = image_binary.copy()
                        image_binary_copy = cv.cvtColor(image_binary_copy, cv.COLOR_GRAY2BGR)
                        # рисуем маркеры в найденых точках
                        for i in corners:
                            cv.drawMarker(image_binary_copy, tuple(i), (0, 255, 0), markerType=cv.MARKER_TILTED_CROSS, thickness=2,
                                          markerSize=50)
                        cv.drawContours(image_binary_copy, [approx], -1, (255, 0, 255), 3)

                        if view_result_flag:
                            cv.imshow("Contour", image_binary_copy)

                        size_x = zeroes_mask.shape[1]  # Размер кадра по х
                        size_y = zeroes_mask.shape[0]  # Размер кадра по у

                        pointsFrame.y = [corners[0][1],
                                         corners[1][1],
                                         corners[2][1],
                                         corners[3][1]]  # Координаты рамки в пикселях x       [1]

                        pointsFrame.x = [corners[0][0],
                                         corners[1][0],
                                         corners[2][0],
                                         corners[3][0]]  # Координаты рамки в пикселях y       [0]

                        dist = np.array([depth_frame[corners[0][1]][corners[0][0]],
                                         depth_frame[corners[1][1]][corners[1][0]],
                                         depth_frame[corners[2][1]][corners[2][0]],
                                         depth_frame[corners[3][1]][corners[3][0]]])
                        # переводим дистанцию в метры
                        dist = dist / 1000

                        # проверяем есть ли нули в массиве дистанций -> отсеиваем итерации с нулями
                        if not 0.0 in dist and np.max(dist) < 4.0:
                        # if not math.isnan(dist.max()):
                            rospy.loginfo("DIST OK")
                            rospy.loginfo(dist)
                            goal_ = calculateGoalPointToFrame(size_x, size_y, pointsFrame, dist, l, height_of_drone, width_of_drone)

                            # print('x : ' + str(goal_.x0) + ', ' + 'y : ' + str(goal_.y0) + ', ' + 'z : ' + str(goal_.z0))

                            #################################
                            # находим координату вектора от точки перед рамкой до точки в центре рамки относительно 0 точки системы координат
                            goal_vect = goal(goal_.x1 - goal_.x0, goal_.y1 - goal_.y0, goal_.z1 - goal_.z0, 0, 0, 0)

                            # находим угол смещения курса коптера @от нормали к плоскости рамки
                            yaw_error = math.acos(((goal_.x1 * goal_vect.x0) + (0 * goal_vect.y0))/(math.hypot(goal_vect.x0, goal_vect.y0) * math.hypot(goal_.x1, 0)))    # обычное скалярное произведение векторов

                            if goal_vect.y0 < 0.0:
                                yaw_error = -yaw_error
                            # останавливаем полет по линии
                            frame_detect_flag.detect_frame = True
                            detect_frame_publisher.publish(frame_detect_flag)

                            try:
                                point0 = Point(x=goal_.x0, y=goal_.y0, z=goal_.z0)
                                point1 = Point(x=goal_.x1, y=goal_.y1, z=goal_.z1)
                                point2 = Point(x=goal_.x1 + 1.5 * math.cos(yaw_error), y=goal_.y1 + 1.5 * math.sin(yaw_error), z=goal_.z1)

                                marker0 = make_marker(point0, 0)
                                marker1 = make_marker(point1, 1)
                                marker2 = make_marker(point2, 2)

                                marker_publisher.publish(marker0)
                                marker_publisher.publish(marker1)
                                marker_publisher.publish(marker2)
                                rospy.loginfo('pub marker')
                            except:
                                pass

                            rospy.loginfo("yaw_error: %s" %yaw_error)
                            #################################

                            #******#
                            # trajectory = transform_cords_3D(drone_pose.pose.position.x, drone_pose.pose.position.y,drone_pose.pose.position.z, 0.0, 0.0, yaw, goal_, yaw_error)
                            # trajectory_publisher(trajectory, yaw_error)
                            #******#
                        else:
                            rospy.loginfo("DIST IS NOT OK!")
                    except:
                        continue
		    hz.sleep()
        if cv.waitKey(1) == 27:  # проверяем была ли нажата кнопка esc
            break

if __name__ == "__main__":
        main()

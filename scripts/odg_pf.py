#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import rospy
from sensor_msgs.msg import LaserScan
from ackermann_msgs.msg import AckermannDriveStamped
from nav_msgs.msg import Odometry

import math
import numpy as np
import time
import csv

import matplotlib.pyplot as plt
from visualization_msgs.msg import Marker, MarkerArray
from f1tenth_gym_ros.msg import RaceInfo

class ODGPF:
    def __init__(self):
        # import Topics
        self.drive_topic = rospy.get_param("drive_topic", "/drive") 
        self.odom_topic = rospy.get_param("odom_topic", "/odom")
        self.scan_topic = rospy.get_param("scan_topic", "/scan")
        self.marker_topic = rospy.get_param("marker_topic", "/marker")
        
        self.rep_count = 0
        self.ackermann_data = AckermannDriveStamped()
        self.PI = rospy.get_param('pi', 3.141592)
        self.MU = rospy.get_param('mu', 0.523)   #1.0
        self.MASS = rospy.get_param('mass', 3.47)
        self.GRAVITY_ACC = rospy.get_param('g', 9.81)
        self.SPEED_MAX = rospy.get_param('max_speed', 20.0)
        self.SPEED_MIN = rospy.get_param('min_speed', 1.5)
        self.RATE = rospy.get_param('rate', 100)
        self.ROBOT_SCALE = rospy.get_param('robot_scale', 0.25)
        self.ROBOT_LENGTH = rospy.get_param('robot_length', 0.325)
        self.LOOK = 5
        self.THRESHOLD = 3.0
        self.FILTER_SCALE = 1.1
        self.scan_range = 0
        self.desired_wp_rt = [0,0]

        self.time_data_file_name = "odg_pf_pp_time_data"
        self.time_data_path = rospy.get_param("time_data_path")
        self.time_data = open(f"{self.time_data_path}/{self.time_data_file_name}.csv", "w", newline="")
        self.time_data_writer = csv.writer(self.time_data)
        self.time_data_writer.writerow("index","time","exe_time")

        self.waypoint_real_path = rospy.get_param('wpt_path', '../map/wp_vegas.csv')
        self.waypoint_delimeter = rospy.get_param('wpt_delimeter', ',')

        self.trj_path = rospy.get_param('trj_path', '')
        self.time_data_path = rospy.get_param('time_data_path', '')

        self.front_idx = 539
        self.detect_range_s = 299
        self.detect_range_e = 779
        self.detect_range = self.detect_range_e - self.detect_range_s
        self.detect_n = 5

        self.safety_threshold = 0
        self.min_idx = 0
        self.f_rep_past_list =[0]*1080
        self.t_start = time.time()
        #self.p = 0.1
        self.w = 0.9
        self.d = 0.05
        self.i = 0.5
        self.steering_min = 5
        self.steering_max = 15

        self.error_past = 0   
        self.current_position_past = 0
        self.steering_angle = 0
        self.set_steering = 0
        self.steering_angle_past = 0

        self.wp_num = 1
        self.waypoints = self.get_waypoint()
        self.wp_index_current = 0
        #self.goal_point = [37.6,-19.1, 0]
        self.nearest_distance = 0

        self.current_position = [0,0,0]
        self.interval = 0.00435
        self.gamma = 0.5
        #self.a_k = 1.2
        self.current_speed = 1.0
        self.set_speed = 0.0
        self.alpha = 0.9

        self.ackermann_data.drive.acceleration = 0
        self.ackermann_data.drive.jerk = 0
        self.ackermann_data.drive.steering_angle = 0
        self.ackermann_data.drive.steering_angle_velocity = 0
        
        rospy.Subscriber("/race_info", RaceInfo, self.update_race_info, queue_size = 10)
        rospy.Subscriber(self.scan_topic, LaserScan, self.subCallback_scan, queue_size = 10)
        rospy.Subscriber(self.odom_topic, Odometry, self.Odome, queue_size = 10)
        self.drive_pub = rospy.Publisher(self.drive_topic, AckermannDriveStamped, queue_size = 10 )

        self.marker_pub = rospy.Publisher(self.marker_topic, Marker, queue_size=10)

        self.mode = 0

        self.idx_temp = 0
        self.flag = False
        self.race_info = None 
        self.lap_time = 0
        self.lap = 0
        self.recording = open('/home/lab/f1tenth_ws/src/local_planning_gnu/utill/recording.csv', 'a')




        # Trajectory Logging
        self.tr_flag = rospy.get_param('logging',False)
        self.logging_idx = 0
        self.race_time = 0

        if self.tr_flag:
            self.trajectory = open(self.trj_path,'w')
    
    def update_race_info(self,race_info):
        """
        header: 
            seq: 2442
            stamp: 
                secs: 1627305621
                nsecs:  19615888
            frame_id: ''
            ego_lap_count: 0.0
            opp_lap_count: 0.0
            ego_elapsed_time: 9.300000190734863
            opp_elapsed_time: 9.300000190734863
            ego_collision: False
            opp_collision: False
        """
        self.race_info = race_info
        self.race_time = race_info.ego_elapsed_time
        
        if self.race_info.ego_lap_count > self.lap:
            print('lap_count',self.race_info.ego_lap_count,'elapsed_time', self.race_info.ego_elapsed_time)
            self.lap += 1
    
    def getDistance(self, a, b):
        dx = a[0] - b[0]
        dy = a[1] - b[1]
        
        return np.sqrt(dx**2 + dy**2)

    def trajectory_logging(self):
        _race_time = self.race_time
        self.trajectory.write(f"{_race_time},")
        self.trajectory.write(f"{self.current_position[0]},")
        self.trajectory.write(f"{self.current_position[1]},")
        self.trajectory.write(f"{self.current_position[2]},")
        self.trajectory.write(f"{self.current_speed}\n")
            
    def transformPoint(self, origin, target):
        theta = self.PI/2 - origin[2]
        dx = target[0] - origin[0]
        dy = target[1] - origin[1]
        dtheta = target[2] + theta
        
        tf_point_x = dx * np.cos(theta) - dy * np.sin(theta)
        tf_point_y = dx * np.sin(theta) + dy * np.cos(theta)
        tf_point_theta = dtheta
        tf_point = [tf_point_x, tf_point_y, tf_point_theta]
        
        return tf_point

    def xyt2rt(self, origin):
        rtpoint = []

        x = origin[0]
        y = origin[1]

        #rtpoint[0] = r, [1] = theta
        rtpoint.append(np.sqrt(x*x + y*y))
        rtpoint.append(np.arctan2(y, x) - (self.PI/2))

        return rtpoint

    def get_waypoint(self):
        file_wps = np.genfromtxt(self.waypoint_real_path, delimiter=self.waypoint_delimeter, dtype='float')
        # params.yaml 파일 수정 부탁드립니다... 제발...

        temp_waypoint = []
        for i in file_wps:
            wps_point = [i[0],i[1],0]
            temp_waypoint.append(wps_point)
            self.wp_num += 1
        # print("wp_num",self.wp_num)
        return temp_waypoint

    def find_desired_wp(self):
        wp_index_temp = self.wp_index_current
        self.nearest_distance = self.getDistance(self.waypoints[wp_index_temp], self.current_position)

        _vel = self.current_speed

        #self.LOOK = 1.5 + (0.3 * _vel)
        self.LOOK = 0.5 + (0.5 * _vel)

        while True:
            wp_index_temp+=1

            if wp_index_temp >= self.wp_num-1:
                wp_index_temp = 0
                # print(self.lap_time)

            temp_distance = self.getDistance(self.waypoints[wp_index_temp], self.current_position)

            if temp_distance < self.nearest_distance:
                self.nearest_distance = temp_distance
                self.wp_index_current = wp_index_temp
            elif ((temp_distance > (self.nearest_distance + self.LOOK*1.2)) or (wp_index_temp == self.wp_index_current)):
                break
        
        temp_distance = 0
        idx_temp = self.wp_index_current
        while True:
            if idx_temp >= self.wp_num-1:
                idx_temp = 0
            temp_distance = self.getDistance(self.waypoints[idx_temp], self.current_position)
            if temp_distance > self.LOOK: break
            idx_temp += 1

        transformed_nearest_point = self.transformPoint(self.current_position, self.waypoints[idx_temp])
        self.desired_wp_rt = self.xyt2rt(transformed_nearest_point)

        self.idx_temp = idx_temp
        marker = Marker()
        marker.header.frame_id = "map"
        marker.header.stamp = rospy.Time.now()
        marker.ns = "mpc"
        marker.id = 2
        marker.type = marker.CUBE
        marker.action = marker.ADD
        marker.pose.position.x = self.waypoints[self.idx_temp][0]
        marker.pose.position.y = self.waypoints[self.idx_temp][1]
        marker.pose.position.z = 0.1
        marker.pose.orientation.x = 0.0
        marker.pose.orientation.y = 0.0
        marker.pose.orientation.z = 0.0
        marker.pose.orientation.w = 1.0
        marker.scale.x = 0.2
        marker.scale.y = 0.2
        marker.scale.z = 0.1
        marker.color.a = 1.0
        marker.color.r = 1.0
        marker.color.g = 0.0
        marker.color.b = 0.0
        # print(self.waypoints[self.idx_temp], self.idx_temp)
        self.marker_pub.publish(marker)

    def define_obstacles(self, scan):
        obstacles = []
        
        i = self.detect_range_s
        d_i = 0
        while True:
            if (i >= self.detect_range_e):
                break
            if scan[i] < self.THRESHOLD:
                
                start_temp = scan[i]
                start_idx_temp = i
                end_temp = start_temp
                end_idx_temp = i
                max_temp = scan[i]
                max_idx_temp = i
                obstacle_count = 1
                
                while ((scan[i] < self.THRESHOLD) and (i+1 < self.detect_range_e)):#self.scan_range
                    i += 1
                    end_temp += scan[i]
                    obstacle_count += 1
                    if scan[i] > max_temp:
                        max_temp = scan[i]
                        max_idx_temp = i
                if scan[i] < self.THRESHOLD:
                    i += 1   
                end_idx_temp = i
                
                # print('start:', start_idx_temp,'end:',end_idx_temp, end=" ")


                distance_obstacle = end_temp/obstacle_count
                
                
                a_k = ((self.THRESHOLD - distance_obstacle)*np.exp(1/2))

                angle_obstacle = (end_idx_temp - start_idx_temp)*self.interval

                sigma_obstacle = np.arctan2((distance_obstacle * np.tan(angle_obstacle/2) + (self.ROBOT_SCALE/2)), distance_obstacle)

                angle_obstacle_center = (int)((end_idx_temp - start_idx_temp)/2) + start_idx_temp 
                angle_obstacle_center = angle_obstacle_center - self.front_idx

                obstacle_inf = [angle_obstacle_center, sigma_obstacle, a_k]
                
                # print('angle_center',angle_obstacle_center,end=' ')
                # print(sigma_obstacle)
                obstacles.append(obstacle_inf)
        
            
            i += 1

        # print(len(obstacles))
        # print()

        return obstacles

    def rep_field(self, obstacles):

        f_rep_list = [0]*self.scan_range # np.zeros(self.scan_range)
        for i in range(len(obstacles)):
            for j in range(self.detect_range_s, self.front_idx):
                f_rep_list[j] += obstacles[i][2] * np.exp((-0.5)*((((j-self.front_idx)*self.interval - obstacles[i][0]*self.interval)**2) / (obstacles[i][1])**2))
            
            for k in range(self.detect_range_e, self.front_idx-1,-1):
                f_rep_list[k] += obstacles[i][2] * np.exp((-0.5)*((((k-self.front_idx)*self.interval - obstacles[i][0]*self.interval)**2) / (obstacles[i][1])**2))

        self.f_rep_list = f_rep_list
        
        #reversed(f_rep_list)
        return f_rep_list

    def att_field(self, goal_point):

        f_att_list = []
        for i in range(self.scan_range):
            idx2deg = (-self.front_idx+i)*self.interval
            f_att = self.gamma * np.fabs(goal_point[1] - idx2deg)
            f_att_list.append(f_att)

        return f_att_list 

    def total_field(self, f_rep_list, f_att_list):
        
        f_total_list = [0]*self.scan_range

        for i in range(self.scan_range):
            f_total_list[i] = f_rep_list[i] + f_att_list[i]

        self.min_idx = np.argmin(f_total_list[self.detect_range_s:self.detect_range_e])+self.detect_range_s

        self.f_total_list = f_total_list
        return self.min_idx

    def angle(self, f_total_list):

        min_f = f_total_list[0]*self.scan_range
        min_f_idx = self.detect_range_s

        for i in range(self.detect_range_s + 1, self.detect_range_e-1):
            if min_f > f_total_list[i]:
                min_f = f_total_list[i]
                min_f_idx = i

        return min_f_idx
    
    def speed_controller(self):
        current_distance = np.fabs(np.average(self.scan_filtered[499:580]))
        if np.isnan(current_distance):
            print("SCAN ERR")
            current_distance = 1.0
        
        if self.current_speed > 10:
            current_distance -= self.current_speed * 0.7
        
        maximum_speed = np.sqrt(2*self.MU * self.GRAVITY_ACC * np.fabs(current_distance)) - 2

        if maximum_speed >= self.SPEED_MAX:
            maximum_speed = self.SPEED_MAX
        
        if self.current_speed <= maximum_speed:
            # ACC
            if self.current_speed >= 10:
                set_speed = self.current_speed + np.fabs((maximum_speed - self.current_speed))
            else:
                set_speed = self.current_speed + np.fabs((maximum_speed - self.current_speed) * self.ROBOT_LENGTH)
        else:
            # set_speed = 0
            set_speed = self.current_speed - np.fabs((maximum_speed - self.current_speed) * 0.2)


        return set_speed

    def main_drive(self, goal):

        self.steering_angle = (-self.front_idx+goal)*self.interval

        controlled_angle = self.steering_angle

        if controlled_angle == 0.0:
            controlled_angle = 0.001

        # LOOK : 0.5 + (0.3 * _vel)   (장애물 or 곡선 part) == 2
        # LOOK이 path_radius에 끼치는 영향
        # -> LOOK이 클수록 스티어링 앵글을 덜꺾음 
        path_radius = self.LOOK**1.25 / (2 * np.sin(controlled_angle))
        steering_angle = np.arctan(self.ROBOT_LENGTH / path_radius)
        # print("input",controlled_angle,"output",steering_angle)

        self.set_speed = self.speed_controller() # determin_speed

        
        self.ackermann_data.drive.steering_angle = steering_angle   
        self.ackermann_data.drive.steering_angle_velocity = 0   
        self.ackermann_data.drive.speed = self.set_speed
        self.ackermann_data.drive.acceleration = 0
        self.ackermann_data.drive.jerk = 0
     
        if np.fabs(self.steering_angle) > 0.5:
            # print("in")
            if np.fabs(self.steering_angle_past - self.steering_angle) > 0.5 :
                steering_angle = self.steering_angle_past#((self.steering_angle+self.steering_angle_past*(0.5))/2)
                # print("to")

        self.current_position_past = self.current_position[2]
        self.steering_angle_past = steering_angle
        self.f_rep_past_list = self.f_rep_list

        self.ackermann_angle = steering_angle
        self.ackermann_speed = self.set_speed

        self.drive_pub.publish(self.ackermann_data)


    def Odome(self, odom_msg):
        qx = odom_msg.pose.pose.orientation.x 
        qy = odom_msg.pose.pose.orientation.y 
        qz = odom_msg.pose.pose.orientation.z
        qw = odom_msg.pose.pose.orientation.w 

        siny_cosp = 2.0 * (qw*qz + qx*qy)
        cosy_cosp = 1.0-2.0*(qy*qy + qz*qz)

        current_position_theta = np.arctan2(siny_cosp, cosy_cosp)
        current_position_x = odom_msg.pose.pose.position.x
        current_position_y = odom_msg.pose.pose.position.y
        # print(current_position_theta)
        self.current_position = [current_position_x,current_position_y, current_position_theta]

        self.find_desired_wp()
        _speed = odom_msg.twist.twist.linear.x
        _steer = odom_msg.twist.twist.angular.z
        self.current_speed = _speed
        self.set_steering = _steer

    def subCallback_scan(self,msg_sub):
        self.scan_angle_min = msg_sub.angle_min
        self.scan_angle_max = msg_sub.angle_max
        self.interval = msg_sub.angle_increment
        self.scan_range = len(msg_sub.ranges)
        self.front_idx = (int)(self.scan_range/2)
        
        self.scan_origin = [0]*self.scan_range
        self.scan_filtered = [0]*self.scan_range
        for i in range(self.scan_range):
            
            self.scan_origin[i] = msg_sub.ranges[i]
            self.scan_filtered[i] = msg_sub.ranges[i]

        for i in range(self.scan_range):           
            if self.scan_origin[i] == 0:
                cont = 0 
                sum = 0
                for j in range(1,21):
                    if i-j >= 0:
                        if self.scan_origin[i-j] != 0:
                            cont += 1
                            sum += self.scan_origin[i-j]
                    if i+j < self.scan_range:
                        if self.scan_origin[i+j] != 0:
                            cont += 1
                            sum += self.scan_origin[i+j]
                self.scan_origin[i] = sum/cont
                self.scan_filtered[i] = sum/cont

        for i in range(self.scan_range - 1):
            if self.scan_origin[i]*self.FILTER_SCALE < self.scan_filtered[i+1]:
		#print('filter')
                unit_length = self.scan_origin[i]*self.interval 
                filter_num = self.ROBOT_SCALE/unit_length

                j = 1
                while j < filter_num + 1:
                    if i+j < self.scan_range:
                        if self.scan_filtered[i+j] > self.scan_origin[i]:
                            self.scan_filtered[i+j] = self.scan_origin[i]
                        else: break
                    else: break 
                    j += 1
        
            elif self.scan_filtered[i] > self.scan_origin[i+1]*self.FILTER_SCALE:
                unit_length = self.scan_origin[i+1]*self.interval
                filter_num = self.ROBOT_SCALE / unit_length

                j = 0
                while j < filter_num + 1:
                    if i-j > 0:
                        if self.scan_filtered[i-j] > self.scan_origin[i+1]:
                            self.scan_filtered[i-j] = self.scan_origin[i+1]
                        else: break
                    else: break
                    j += 1

    def driving(self):
        loop = 0
        rate = rospy.Rate(self.RATE)
        tn = time.time()
        self.t_start = time.time()
        # self.s1 = [0]*750
        # self.s2 = [0]*750
        # self.s3 = [0]*750
        # self.s = np.arange(750)

        #speed monitoring
        # self.b1 = [0]*750
        # self.b2 = [0]*750
        # self.b = np.arange(750)
        
        self.c1 = [0]*(self.detect_range*self.detect_n)
        self.c2 = [0]*(self.detect_range*self.detect_n)
        self.c3 = [0]*(self.detect_range*self.detect_n)
        self.c = np.arange(self.detect_range*self.detect_n)
        
        i = 0
        while not rospy.is_shutdown():
            i += 1

            if self.scan_range == 0: continue
            tn0 = time.time()
            loop += 1

            obstacles = self.define_obstacles(self.scan_filtered)

            rep_list = self.rep_field(obstacles)
            att_list = self.att_field(self.desired_wp_rt)
            total_list = self.total_field(rep_list, att_list)

            desired_angle = total_list#self.angle(total_list)
            self.main_drive(desired_angle)
            
            tn1 = time.time()
            """
                tn:  initinalize Time
                tn0: driving loop start Time
                tn1: driving loop final Time
            """
            self.time_data_writer.writerow([loop, tn1-tn, tn1-tn0])
            if self.tr_flag:
                self.trajectory_logging()
            if i % 10 == 0:
                # del self.s1[0]
                # del self.s2[0]
                # del self.s3[0]
                
                # del self.b1[0]
                # del self.b2[0]
                
                del self.c1[0:self.detect_range]
                del self.c2[0:self.detect_range]
                del self.c3[0:self.detect_range]

                # self.s1.append(self.f_total_list[total_list])
                # self.s2.append(att_list[total_list])
                # self.s3.append(rep_list[total_list])

                # self.b1.append(self.current_speed)
                # self.b2.append(self.set_speed)

                self.c1 = self.c1 + self.f_total_list[self.detect_range_s:self.detect_range_e][::-1]
                self.c2 = self.c2 + att_list[self.detect_range_s:self.detect_range_e][::-1]
                self.c3 = self.c3 + rep_list[self.detect_range_s:self.detect_range_e][::-1]

                # # ####################
                # plt.subplot(1,1,1)
                # plt.plot(self.c,self.c1,color = 'black', label ='total field',linewidth=3.0)
                # plt.xticks([self.detect_range*0,self.detect_range*1,self.detect_range*2,self.detect_range*3,self.detect_range*4,self.detect_range*self.detect_n])
                # plt.legend(bbox_to_anchor=(1,1))
                # plt.ylim([0, 3])
                # plt.grid()

                # #plt.subplot(1,1,1)
                # plt.plot(self.c,self.c2,color = 'b',label ='att field',linewidth=3.0)
                # plt.legend(bbox_to_anchor=(1,1))
                # plt.xticks([self.detect_range*0,self.detect_range*1,self.detect_range*2,self.detect_range*3,self.detect_range*4,self.detect_range*self.detect_n])
                # # plt.ylim([0, 5])
                # plt.grid()

                # #plt.subplot(1,1,1)
                # plt.plot(self.c,self.c3,color = 'r',label ='rep field',linewidth=3.0)
                # plt.legend(bbox_to_anchor=(1,1))
                # plt.xticks([self.detect_range*0,self.detect_range*1,self.detect_range*2,self.detect_range*3,self.detect_range*4,self.detect_range*self.detect_n])
                # # plt.ylim([0, 5])
                # plt.grid()
                # plt.pause(0.001)
                # plt.clf()
                # print(self.steering_angle_past)
                # # ##################
   
        
            rate.sleep()

        if self.tr_flag:
            print(self.race_time, self.race_info.ego_collision)

            self.recording.write(f"race_time : {np.round(self.race_time,4),self.race_info.ego_collision}\n")

            self.trajectory.close()

if __name__ == '__main__':
    rospy.init_node("driver_odg_pf")
    A = ODGPF()
    A.driving()
    rospy.spin()
